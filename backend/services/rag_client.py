"""
RAG Client for retrieving document chunks from RAG API.

This module provides a wrapper around the RAG API running on AWS.
"""

import requests
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RAGClient:
    """Client for interacting with the RAG API service."""

    def __init__(self, rag_url: str = "http://ec2-18-212-13-217.compute-1.amazonaws.com"):
        """
        Initialize RAG client.

        Args:
            rag_url: Base URL of the RAG API service
        """
        self.rag_url = rag_url
        self.retrieve_endpoint = f"{rag_url}/api/retrieve"
        self.health_endpoint = f"{rag_url}/api/health"
        self.stats_endpoint = f"{rag_url}/api/stats"

    def check_health(self, timeout: int = 5) -> bool:
        """
        Check if RAG API is running and healthy.

        Args:
            timeout: Request timeout in seconds

        Returns:
            True if healthy, False otherwise
        """
        try:
            response = requests.get(self.health_endpoint, timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                logger.info(f"RAG API health check: {data.get('status')}")
                return data.get('status') == 'healthy'
            return False
        except requests.RequestException as e:
            logger.error(f"RAG API health check failed: {str(e)}")
            return False

    def retrieve_chunks(
        self,
        query: str,
        top_k: int = 5,
        timeout: int = 10,
        retry: bool = True
    ) -> Dict[str, Any]:
        """
        Retrieve relevant document chunks from RAG API.

        Args:
            query: User's question or search query
            top_k: Number of chunks to retrieve (1-20)
            timeout: Request timeout in seconds
            retry: Whether to retry on failure

        Returns:
            Dictionary containing:
                - success: bool
                - chunks: List of chunk dictionaries
                - metadata: Performance and routing info
                - error: Error message if failed

        Raises:
            ConnectionError: If RAG API is not reachable
            TimeoutError: If request times out
        """
        start_time = datetime.now()

        # Check health first
        if not self.check_health(timeout=3):
            error_msg = "RAG API is not running or unhealthy"
            logger.error(error_msg)
            return {
                "success": False,
                "chunks": [],
                "error": error_msg,
                "query": query
            }

        try:
            # Make the request
            response = requests.post(
                self.retrieve_endpoint,
                json={'query': query, 'top_k': top_k},
                headers={'Content-Type': 'application/json'},
                timeout=timeout
            )

            elapsed = (datetime.now() - start_time).total_seconds()

            if response.status_code != 200:
                error_msg = response.json().get('error', 'Unknown error')
                logger.error(f"RAG API returned error: {error_msg}")
                return {
                    "success": False,
                    "chunks": [],
                    "error": error_msg,
                    "query": query
                }

            data = response.json()
            chunks = data.get('chunks', [])

            logger.info(
                f"Retrieved {len(chunks)} chunks for query in {elapsed:.2f}s"
            )

            return {
                "success": True,
                "chunks": chunks,
                "query": query,
                "total_chunks": data.get('total_chunks', len(chunks)),
                "routing_info": data.get('routing_info', {}),
                "performance": data.get('performance', {}),
                "retrieval_time": elapsed
            }

        except requests.Timeout as e:
            error_msg = f"RAG API request timed out after {timeout}s"
            logger.error(error_msg)

            # Retry once if enabled
            if retry:
                logger.info("Retrying RAG API request...")
                return self.retrieve_chunks(
                    query=query,
                    top_k=top_k,
                    timeout=timeout,
                    retry=False  # Don't retry again
                )

            return {
                "success": False,
                "chunks": [],
                "error": error_msg,
                "query": query
            }

        except requests.RequestException as e:
            error_msg = f"RAG API request failed: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "chunks": [],
                "error": error_msg,
                "query": query
            }

    def format_chunks_as_context(
        self,
        chunks: List[Dict[str, Any]],
        include_sources: bool = True,
        include_similarity: bool = False
    ) -> str:
        """
        Format retrieved chunks into a context string for LLM.

        Args:
            chunks: List of chunk dictionaries from retrieve_chunks()
            include_sources: Whether to include source document names
            include_similarity: Whether to include similarity scores

        Returns:
            Formatted context string
        """
        if not chunks:
            return ""

        formatted_chunks = []

        for i, chunk in enumerate(chunks, 1):
            content = chunk.get('content', '')
            source = chunk.get('source', 'unknown')
            similarity = chunk.get('similarity', 0.0)

            if include_sources and include_similarity:
                header = f"[Document {i}: {source} | Similarity: {similarity:.2f}]"
            elif include_sources:
                header = f"[Document {i}: {source}]"
            else:
                header = f"[Document {i}]"

            formatted_chunks.append(f"{header}\n{content}")

        return "\n\n---\n\n".join(formatted_chunks)

    def get_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get RAG system statistics.

        Returns:
            Dictionary with collection counts and statistics, or None if failed
        """
        try:
            response = requests.get(self.stats_endpoint, timeout=5)
            if response.status_code == 200:
                return response.json()
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get RAG stats: {str(e)}")
            return None

    def extract_sources(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """
        Extract unique source document names from chunks.

        Args:
            chunks: List of chunk dictionaries

        Returns:
            List of unique source document names
        """
        sources = set()
        for chunk in chunks:
            source = chunk.get('source')
            if source:
                sources.add(source)
        return sorted(list(sources))

    def retrieve_chunks_for_section(
        self,
        section_title: str,
        questions: List[Dict[str, Any]],
        company_data: Dict[str, Any],
        configuration: Dict[str, Any] = None,
        previous_context: str = "",
        top_k: int = 15,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        Retrieve chunks for an entire section with comprehensive query.

        This method builds a comprehensive query covering all questions in the section
        and retrieves chunks in a single RAG API call.

        Args:
            section_title: Title of the section (e.g., "BUSINESS STRUCTURE")
            questions: List of question objects in section
            company_data: Company information dictionary
            configuration: User configuration from intake form
            previous_context: Context from previous sections
            top_k: Number of chunks to retrieve
            timeout: Request timeout in seconds

        Returns:
            Dictionary containing chunks and metadata
        """
        # Build comprehensive section query
        section_query = self._build_section_query(
            section_title=section_title,
            questions=questions,
            company_data=company_data,
            configuration=configuration,
            previous_context=previous_context
        )

        logger.info(f"Retrieving {top_k} chunks for section '{section_title}' with {len(questions)} questions")

        # Retrieve chunks
        result = self.retrieve_chunks(
            query=section_query,
            top_k=top_k,
            timeout=timeout
        )

        # Add section metadata
        if result.get('success'):
            result['section_title'] = section_title
            result['num_questions'] = len(questions)
            result['section_query'] = section_query

        return result

    def _build_section_query(
        self,
        section_title: str,
        questions: List[Dict[str, Any]],
        company_data: Dict[str, Any],
        configuration: Dict[str, Any] = None,
        previous_context: str = ""
    ) -> str:
        """
        Build comprehensive RAG query for section-level retrieval.

        Query format:
        Section: {section_title}
        Company: {company_name} | Sector: {sector} | Cloud: {cloud_provider}
        Configuration: {compliance_standards}, {environments}, {regions}, ...

        Questions to answer:
        1. {question_1_text}
           Options: {option1}, {option2}...
        2. {question_2_text}
        ...

        Context from previous sections:
        {compressed_previous_context}

        Retrieve {cloud_provider} Landing Zone best practices covering:
        - {derived_topics}

        Args:
            section_title: Section title
            questions: List of question objects
            company_data: Company information
            configuration: User configuration from intake form
            previous_context: Previous section context

        Returns:
            Formatted section query string
        """
        # Extract company info from nested 'data' structure
        # The company_data has structure: {"success": True, "company_name": "...", "data": {...}}
        company_name = company_data.get('company_name', 'Unknown')

        # Get the nested data object
        company_info = company_data.get('data', {})

        # Extract fields from nested structure
        sector = company_info.get('Sector', 'Unknown')
        country_of_origin = company_info.get('Country of origin', '')

        # Cloud provider from configuration (not in company data)
        cloud_provider = configuration.get('cloud_provider', 'AWS') if configuration else 'AWS'

        # Build configuration section
        config_parts = []
        if configuration:
            if configuration.get('compliance_standards'):
                standards = configuration['compliance_standards']
                if isinstance(standards, list):
                    config_parts.append(f"Compliance: {', '.join(standards)}")
                else:
                    config_parts.append(f"Compliance: {standards}")
            if configuration.get('environments'):
                envs = configuration['environments']
                if isinstance(envs, list):
                    config_parts.append(f"Environments: {', '.join(envs)}")
            if configuration.get('regions'):
                regions = configuration['regions']
                if isinstance(regions, list):
                    config_parts.append(f"Regions: {', '.join(regions)}")

        config_line = " | ".join(config_parts) if config_parts else ""

        # Build questions list
        questions_text = []
        for i, question in enumerate(questions, 1):
            question_text = question.get('question', '')
            options = question.get('options', [])

            if options:
                # Format options
                option_labels = [opt.get('label', '') for opt in options]
                options_str = ', '.join(option_labels[:5])  # Limit to first 5 options
                if len(option_labels) > 5:
                    options_str += ', ...'
                questions_text.append(f"{i}. {question_text}\n   Options: {options_str}")
            else:
                questions_text.append(f"{i}. {question_text}")

        questions_section = '\n'.join(questions_text)

        # Build context section
        context_section = ""
        if previous_context:
            # Limit previous context to ~500 chars for query
            context_preview = previous_context[:500]
            if len(previous_context) > 500:
                context_preview += "..."
            context_section = f"\n\nContext from previous sections:\n{context_preview}"

        # Derive topics from section and questions
        topics = self._derive_topics_from_section(section_title, questions, cloud_provider)
        topics_section = '\n'.join([f"- {topic}" for topic in topics])

        # Build final query with configuration if available
        config_section = ""
        if config_line:
            config_section = f"\nConfiguration: {config_line}"

        # Build company line with country if available
        company_line = f"{company_name} | Sector: {sector} | Cloud: {cloud_provider}"
        if country_of_origin:
            company_line += f" | Origin: {country_of_origin}"

        query = f"""Section: {section_title}
Company: {company_line}{config_section}

Questions to answer:
{questions_section}{context_section}

Retrieve {cloud_provider} Landing Zone best practices covering:
{topics_section}"""

        return query

    def _derive_topics_from_section(
        self,
        section_title: str,
        questions: List[Dict[str, Any]],
        cloud_provider: str
    ) -> List[str]:
        """
        Derive relevant topics from section title and questions.

        Args:
            section_title: Section title
            questions: List of questions
            cloud_provider: Cloud provider (AWS, Azure, GCP)

        Returns:
            List of topic strings
        """
        topics = []

        # Map section titles to topics
        section_topic_map = {
            "BUSINESS STRUCTURE": [
                f"{cloud_provider} Organizations account structure strategies",
                "Multi-account architecture patterns",
                "Environment isolation and separation"
            ],
            "Compliance and legal requirements": [
                "Regulatory compliance frameworks",
                "Data residency and sovereignty",
                "Security and audit controls"
            ],
            "Audit and Log Requirements": [
                "Centralized logging strategies",
                "Audit trail requirements",
                "Log retention and analysis"
            ],
            "NETWORK REQUIREMENTS": [
                "Network architecture and connectivity",
                "VPN and hybrid cloud networking",
                "Network security and segmentation"
            ],
            "DISASTER RECOVERY": [
                "Backup and recovery strategies",
                "Business continuity planning",
                "RTO and RPO requirements"
            ]
        }

        # Get topics for section
        if section_title in section_topic_map:
            topics = section_topic_map[section_title]
        else:
            # Generic topics based on section title
            topics = [
                f"{cloud_provider} best practices for {section_title.lower()}",
                "Implementation guidelines and recommendations",
                "Security and compliance considerations"
            ]

        return topics


# Singleton instance
_rag_client_instance: Optional[RAGClient] = None


def get_rag_client() -> RAGClient:
    """
    Get singleton RAG client instance.

    Returns:
        Shared RAGClient instance
    """
    global _rag_client_instance
    if _rag_client_instance is None:
        _rag_client_instance = RAGClient()
    return _rag_client_instance
